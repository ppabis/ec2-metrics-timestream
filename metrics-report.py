import boto3, os, time, requests

"""
This script runs in a loop, collects CPU, Memory and root filesystem metrics and
sends it to Timestream.
"""

def get_cpu() -> list[float]:
    """
    Get average CPU utilization per core
    Based on: https://www.idnt.net/en-US/kb/941772
    """
    with open('/proc/stat') as f:
        lines = f.readlines()
    # Leave only each CPU core
    lines = [line.rstrip() for line in lines if line.startswith('cpu') and not line.startswith('cpu ')]
    # Split each line into values
    values = [line.split() for line in lines]
    # Convert to int
    values = [[int(v) for v in value[1:]] for value in values]
    # Get second measurement
    time.sleep(0.1)
    with open('/proc/stat') as f:
        lines = f.readlines()
    # Leave only each CPU core
    lines = [line.rstrip() for line in lines if line.startswith('cpu') and not line.startswith('cpu ')]
    values2 = [line.split() for line in lines]
    values2 = [[int(v) for v in value[1:]] for value in values2]
    
    total_deltas = [(sum(values2[i]) - sum(values[i])) for i in range(len(values))]
    total_idle = [(values2[i][3] - values[i][3]) for i in range(len(values))]
    total_used = [(total_deltas[i] - total_idle[i]) for i in range(len(values))]
    total_usage = [(total_used[i] / total_deltas[i]) * 100 for i in range(len(values))]
    return total_usage

def get_memory() -> (float, float, float):
    """
    Get memory utilization: (buffered, free, used) as % of total memory
    """
    # Returns something like:
    #               total        used        free      shared  buff/cache   available
    #Mem:             427         138          84           0         204         279
    #Swap:            426           0         426
    #Total:           854         138         511
    mem = os.popen("free -t -m").readlines()[1]
    values = mem.split()
    total = float(values[1])
    used_pct = float(values[2]) / total * 100
    free_pct = float(values[3]) / total * 100
    buffer_pct = float(values[5]) / total * 100

    return (buffer_pct, free_pct, used_pct)

def get_disk() -> (float, float):
    """
    Get disk utilization: (used, free) as % of total disk space
    """
    # Returns something like:
    # Filesystem     1K-blocks    Used Available Use% Mounted on
    # /dev/nvme0n1p1   8311788 1770492   6541296  22% /
    disk = os.popen("df /").readlines()[1]
    values = disk.split()
    total = float(values[1])
    used_pct = float(values[2]) / total * 100
    free_pct = float(values[3]) / total * 100

    return (used_pct, free_pct)

def main():
    database_name = os.environ['TS_DATABASE']
    # Ask IMDSv2 for Instance ID
    token = requests.put('http://169.254.169.254/latest/api/token', headers={'X-aws-ec2-metadata-token-ttl-seconds': '60'}).text
    instance_id = requests.get('http://169.254.169.254/latest/meta-data/instance-id', headers={'X-aws-ec2-metadata-token': token}).text
    region = requests.get('http://169.254.169.254/latest/meta-data/placement/region', headers={'X-aws-ec2-metadata-token': token}).text

    dimensions = [ {'Name': 'InstanceId', 'Value': instance_id} ]
    
    ts = boto3.client('timestream-write', region_name=region)
    while True:
        cpu = get_cpu()
        memory = get_memory()
        disk = get_disk()

        cpu_records = [
            {
                'Dimensions': dimensions + [{'Name': 'Core', 'Value': str(i)}],
                'MeasureName': 'cpu_utilization',
                'MeasureValue': str(cpu[i]),
                'MeasureValueType': 'DOUBLE',
                'Time': str(int(time.time() * 1000)),
                'TimeUnit': 'MILLISECONDS',
            } for i in range(len(cpu))
        ]

        memory_records = [
            {
                'Dimensions': dimensions,
                'MeasureName': 'memory_buffered',
                'MeasureValue': str(memory[0]),
                'MeasureValueType': 'DOUBLE',
                'Time': str(int(time.time() * 1000)),
                'TimeUnit': 'MILLISECONDS',
            },
            {
                'Dimensions': dimensions,
                'MeasureName': 'memory_free',
                'MeasureValue': str(memory[1]),
                'MeasureValueType': 'DOUBLE',
                'Time': str(int(time.time() * 1000)),
                'TimeUnit': 'MILLISECONDS',
            },
            {
                'Dimensions': dimensions,
                'MeasureName': 'memory_used',
                'MeasureValue': str(memory[2]),
                'MeasureValueType': 'DOUBLE',
                'Time': str(int(time.time() * 1000)),
                'TimeUnit': 'MILLISECONDS',
            }
        ]

        disk_records = [
            {
                'Dimensions': dimensions,
                'MeasureName': 'disk_used',
                'MeasureValue': str(disk[0]),
                'MeasureValueType': 'DOUBLE',
                'Time': str(int(time.time() * 1000)),
                'TimeUnit': 'MILLISECONDS',
            },
            {
                'Dimensions': dimensions,
                'MeasureName': 'disk_free',
                'MeasureValue': str(disk[1]),
                'MeasureValueType': 'DOUBLE',
                'Time': str(int(time.time() * 1000)),
                'TimeUnit': 'MILLISECONDS',
            }
        ]

        ts.write_records(DatabaseName=database_name, TableName='CpuUtilization', Records=cpu_records)
        ts.write_records(DatabaseName=database_name, TableName='MemoryUtilization', Records=memory_records)
        ts.write_records(DatabaseName=database_name, TableName='DiskUsed', Records=disk_records)
        time.sleep(0.2)


if __name__ == '__main__':
    main()