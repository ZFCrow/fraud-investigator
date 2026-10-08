# how the checkpoint works
2 things to check 
1) checkpoint.txt 
2) offset.txt

this logic works under the assumption that the activities logs added are always added sequentially, there wont be future additions to the AL table with earlier dated logs, as such, every new ingestion checks the timestamp and ONLY pulls logs that's later than that *TIMESTAMP*, which was the latest timestamp we found in the previous ingestion.

after each ingestion completes, we add a record to the checkpoint.txt and the version number for that ingestion/table

DURING INGESTION, offset get continuously added to the offset.txt with that verion (IN PROGRESS VERSION) 

so if the latest record of offset has the same version as checkpoint.txt, it means the offset were for the completed version and theres no need to offset for this new run

else if offset version > checkpoint version, the previous run was not completed and stopped midway ==> we go and get the records the last run would have gotten , which was logs LATER than the last checkpoint noted timestamp + OFFSET the records from the offset.txt!