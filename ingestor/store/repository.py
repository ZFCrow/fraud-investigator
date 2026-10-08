from abc import ABC, abstractmethod

class ISessionIngestionRepository(ABC) : 

    @abstractmethod
    def get_logs_since():
        """Fetch logs since the given timestamp. 
        If no timestamp is provided, fetch all logs.
        to be implemented by a specific database repository ALONGISDE the type of domain model it returns.
        for exmaple: activitylogs grouped into sessions or all activity logs individually. 
        The repository must return a domain model that is compatible with the ingestion strategy that will consume it. 
        """
        ...

    @abstractmethod 
    def _to_domain(self, raw_data):
        """Convert raw data from the database into a domain model.
        This method should be implemented by the concrete repository to convert the raw data fetched from the database into a domain model that is compatible with the ingestion strategy.
        """
        ...  


    