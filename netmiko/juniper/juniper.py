import re
import time

from netmiko.base_connection import BaseConnection
from netmiko.scp_handler import BaseFileTransfer


class JuniperBase(BaseConnection):
    """
    Implement methods for interacting with Juniper Networks devices.

    Disables `enable()` and `check_enable_mode()`
    methods.  Overrides several methods for Juniper-specific compatibility.
    """

    def __init__(self, *args, **kwargs):
        # Cisco-IOS defaults to fast_cli=True and legacy_mode=False
        kwargs.setdefault("fast_cli", True)
        kwargs.setdefault("_legacy_mode", False)
        return super().__init__(*args, **kwargs)

    def session_preparation(self):
        """Prepare the session after the connection has been established."""
        self.enter_cli_mode()
        cmd = "set cli screen-width 511"
        self.set_terminal_width(command=cmd, pattern=r"Screen width set to")
        # Overloading disable_paging which is confusing
        self.disable_paging(
            command="set cli complete-on-space off",
            pattern=r"Disabling complete-on-space",
        )
        self.disable_paging(
            command="set cli screen-length 0", pattern=r"Screen length set to"
        )
        self.set_base_prompt()

    def _enter_shell(self):
        """Enter the Bourne Shell."""
        return self.send_command("start shell sh", expect_string=r"[\$#]")

    def _return_cli(self):
        """Return to the Juniper CLI."""
        return self.send_command("exit", expect_string=r"[#>]")

    def enter_cli_mode(self):
        """Check if at shell prompt root@ and go into CLI."""
        delay_factor = self.select_delay_factor(delay_factor=0)
        count = 0
        cur_prompt = ""
        while count < 50:
            self.write_channel(self.RETURN)
            time.sleep(0.1 * delay_factor)
            cur_prompt = self.read_channel()
            if re.search(r"root@", cur_prompt) or re.search(r"^%$", cur_prompt.strip()):
                self.write_channel("cli" + self.RETURN)
                time.sleep(0.3 * delay_factor)
                self.clear_buffer()
                break
            elif ">" in cur_prompt or "#" in cur_prompt:
                break
            count += 1

    def check_enable_mode(self, *args, **kwargs):
        """No enable mode on Juniper."""
        pass

    def enable(self, *args, **kwargs):
        """No enable mode on Juniper."""
        pass

    def exit_enable_mode(self, *args, **kwargs):
        """No enable mode on Juniper."""
        pass

    def check_config_mode(self, check_string="]"):
        """Checks if the device is in configuration mode or not."""
        return super().check_config_mode(check_string=check_string)

    def config_mode(
        self,
        config_command: str = "configure",
        pattern: str = r"Entering configuration mode",
        re_flags: int = 0,
    ) -> str:
        """Enter configuration mode."""
        return super().config_mode(
            config_command=config_command, pattern=pattern, re_flags=re_flags
        )

    def exit_config_mode(self, exit_config="exit configuration-mode"):
        """Exit configuration mode."""
        output = ""
        if self.check_config_mode():
            output = self.send_command_timing(
                exit_config, strip_prompt=False, strip_command=False
            )
            if "Exit with uncommitted changes?" in output:
                output += self.send_command_timing(
                    "yes", strip_prompt=False, strip_command=False
                )
            if self.check_config_mode():
                raise ValueError("Failed to exit configuration mode")
        return output

    def commit(
        self,
        confirm=False,
        confirm_delay=None,
        check=False,
        comment="",
        and_quit=False,
        delay_factor=1,
    ):
        """
        Commit the candidate configuration.

        Commit the entered configuration. Raise an error and return the failure
        if the commit fails.

        Automatically enters configuration mode

        default:
            command_string = commit
        check and (confirm or confirm_dely or comment):
            Exception
        confirm_delay and no confirm:
            Exception
        confirm:
            confirm_delay option
            comment option
            command_string = commit confirmed or commit confirmed <confirm_delay>
        check:
            command_string = commit check

        """
        delay_factor = self.select_delay_factor(delay_factor)

        # Commit is very slow so this is needed.
        if delay_factor < 1:
            if not self._legacy_mode and self.fast_cli:
                delay_factor = 1

        if check and (confirm or confirm_delay or comment):
            raise ValueError("Invalid arguments supplied with commit check")

        if confirm_delay and not confirm:
            raise ValueError(
                "Invalid arguments supplied to commit method both confirm and check"
            )

        # Select proper command string based on arguments provided
        command_string = "commit"
        commit_marker = "commit complete"
        if check:
            command_string = "commit check"
            commit_marker = "configuration check succeeds"
        elif confirm:
            if confirm_delay:
                command_string = "commit confirmed " + str(confirm_delay)
            else:
                command_string = "commit confirmed"
            commit_marker = "commit confirmed will be automatically rolled back in"

        # wrap the comment in quotes
        if comment:
            if '"' in comment:
                raise ValueError("Invalid comment contains double quote")
            comment = f'"{comment}"'
            command_string += " comment " + comment

        if and_quit:
            command_string += " and-quit"

        # Enter config mode (if necessary)
        output = self.config_mode()
        # and_quit will get out of config mode on commit

        if and_quit:
            expect_string = re.escape(self.base_prompt)
        else:
            expect_string = None

        try:
            fast_cli_state = self.fast_cli
            self.fast_cli = False
            output += self.send_command(
                command_string,
                expect_string=expect_string,
                strip_prompt=False,
                strip_command=False,
                delay_factor=delay_factor,
            )
        finally:
            self.fast_cli = fast_cli_state

        if commit_marker not in output:
            raise ValueError(f"Commit failed with the following errors:\n\n{output}")

        return output

    def strip_prompt(self, *args, **kwargs):
        """Strip the trailing router prompt from the output."""
        a_string = super().strip_prompt(*args, **kwargs)
        return self.strip_context_items(a_string)

    def strip_context_items(self, a_string):
        """Strip Juniper-specific output.

        Juniper will also put a configuration context:
        [edit]

        and various chassis contexts:
        {master:0}, {backup:1}

        This method removes those lines.
        """
        strings_to_strip = [
            r"\[edit.*\]",
            r"\{master:.*\}",
            r"\{backup:.*\}",
            r"\{line.*\}",
            r"\{primary.*\}",
            r"\{secondary.*\}",
        ]

        response_list = a_string.split(self.RESPONSE_RETURN)
        last_line = response_list[-1]

        for pattern in strings_to_strip:
            if re.search(pattern, last_line):
                return self.RESPONSE_RETURN.join(response_list[:-1])
        return a_string

    def cleanup(self, command="exit"):
        """Gracefully exit the SSH session."""
        try:
            # The pattern="" forces use of send_command_timing
            if self.check_config_mode(pattern=""):
                self.exit_config_mode()
        except Exception:
            pass
        # Always try to send final 'exit' (command)
        self._session_log_fin = True
        self.write_channel(command + self.RETURN)


class JuniperSSH(JuniperBase):
    pass


class JuniperTelnet(JuniperBase):
    def __init__(self, *args, **kwargs):
        default_enter = kwargs.get("default_enter")
        kwargs["default_enter"] = "\r\n" if default_enter is None else default_enter
        super().__init__(*args, **kwargs)


class JuniperFileTransfer(BaseFileTransfer):
    """Juniper SCP File Transfer driver."""

    def __init__(
        self,
        ssh_conn,
        source_file,
        dest_file,
        file_system="/var/tmp",
        direction="put",
        **kwargs,
    ):
        return super().__init__(
            ssh_conn=ssh_conn,
            source_file=source_file,
            dest_file=dest_file,
            file_system=file_system,
            direction=direction,
            **kwargs,
        )

    def remote_space_available(self, search_pattern=""):
        """Return space available on remote device."""
        return self._remote_space_available_unix(search_pattern=search_pattern)

    def check_file_exists(self, remote_cmd=""):
        """Check if the dest_file already exists on the file system (return boolean)."""
        return self._check_file_exists_unix(remote_cmd=remote_cmd)

    def remote_file_size(self, remote_cmd="", remote_file=None):
        """Get the file size of the remote file."""
        return self._remote_file_size_unix(
            remote_cmd=remote_cmd, remote_file=remote_file
        )

    def remote_md5(self, base_cmd="file checksum md5", remote_file=None):
        return super().remote_md5(base_cmd=base_cmd, remote_file=remote_file)

    def enable_scp(self, cmd=None):
        raise NotImplementedError

    def disable_scp(self, cmd=None):
        raise NotImplementedError
