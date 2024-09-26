"""Equipment exception base class."""


class EquipmentBaseException(Exception):
    """Base exception class for Equipment errors.

    This exception class inherits from Exception and serves as the base for all
    exceptions related to Equipment operations.
    """


class EquipmentRuntimeError(EquipmentBaseException):
    """Exception raised for Equipment runtime errors.

    This exception is a subclass of EquipmentBaseException and is raised when there
    is a runtime error during Equipment operations.
    """
