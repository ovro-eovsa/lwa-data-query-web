#!/bin/bash

source ~/.bashrc
source /home/xychen/pyenvx/bin/activate

sh_path="/home/xychen/lwa-data-query-web/utils"

# Date, "YYYY-MM-DD" format for the daily movie generation
start_date=$(date -d "yesterday" +%Y-%m-%d)
end_date=$(date -d "today" +%Y-%m-%d)

# "YYYY-MM-DDTHH:MM:SS" format for the lwadata2sql
start_datetime=$(date -d "yesterday" +%Y-%m-%dT12:00:00)
end_datetime=$(date -d "today" +%Y-%m-%dT03:00:00)

# Run the commands
# python "$sh_path/lwa-query-web_utils.py" --gen movie-daily --start "$start_date" --end "$end_date"
python "$sh_path/lwadata2sql.py" --start "$start_datetime" --end "$end_datetime"
