# data602_assignment3


Please use following command to run docker image:

docker run --name web -it --rm -p 5000:5000 lidiia25/data602_3 /bin/bash -c "cd /var/www; mongod --fork --syslog; mongoimport --db data602 --collection balance --file balance.json; python3 server.py"

https://hub.docker.com/r/lidiia25/data602_3/

