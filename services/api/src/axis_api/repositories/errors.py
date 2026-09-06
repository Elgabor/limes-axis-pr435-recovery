"""Persistence exceptions shared by the facade and aggregate implementations."""


class PersistenceRecordNotFound(LookupError):
    pass
