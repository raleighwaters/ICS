#!/usr/bin/env bash

source /app/script/test_common.sh

RES_FILES=/app/data/res

cmd=${1}
resource=${2}
time=$(date +%H:%M:%S)

resource_online()
{
    resource_name=${1}
    echo "1" > ${RES_FILES}/${resource_name}
}

resource_offline()
{
    resource_name=$1
    echo "0" > ${RES_FILES}/${resource_name}
}

get_resource_state()
{
    resource_name=$1
    state=$(cat ${RES_FILES}/${resource_name})
    if [[ "${state}" -eq "1" ]]; then
        exit 110
    else
        exit 100
    fi
}

# Get a random number for sleep time to simulate more real-world conditions
#sleep_time=$(shuf -i 1-10 -n 1)
sleep_time=0.5

# Initialized resource as offline
if [ ! -f ${RES_FILES}/${resource} ]; then
    resource_offline ${resource}
fi

case ${cmd} in
    "start") echo "${time} starting resource ${resource}";
            resource_online ${resource};
            sleep ${sleep_time};
            exit 0;;
    "stop")  echo "${time} stopping resource ${resource}";
             resource_offline ${resource};
             sleep ${sleep_time};
             exit 0;;
    "monitor")  echo "${time} monitoring resource ${resource}";
                sleep ${sleep_time};
                get_resource_state ${resource};;
    *) exit 1;;
esac
