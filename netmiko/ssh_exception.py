from paramiko.ssh_exception import SSHException
from paramiko.ssh_exception import AuthenticationException


class NetmikoTimeoutException(SSHException):
    """SSH session timed trying to connect to the device."""

    pass


class NetmikoAuthenticationException(AuthenticationException):
    """SSH authentication exception based on Paramiko AuthenticationException."""

    pass


class NetmikoBaseException(Exception):
    """General base exception except for exceptions that inherit from Paramiko."""

    pass


class ConfigInvalidException(NetmikoBaseException):
    """Exception raised for invalid configuration error."""

    pass


class ReadException(NetmikoBaseException):
    """General exception indicating an error occurred during a Netmiko read operation."""

    pass


NetMikoTimeoutException = NetmikoTimeoutException
NetMikoAuthenticationException = NetmikoAuthenticationException
