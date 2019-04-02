from collections import deque
from datetime import datetime
from time import time, sleep
import psutil
import sys
import os
import errno
import subprocess
import json
import socket
import boto3
import threading


def get_datetime_string():
    """
    Generate a datetime string. Useful for making output folders names that never conflict.
    """
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def get_date_string():
    """
    Generate a date string. Useful for identifying output folders.
    """
    return datetime.now().strftime("%Y%m%d")


def get_instance_identification():
    """
    Gets an identifier for an instance.  Gets EC2 instanceId if possible, else local hostname
    """
    instance_id = socket.gethostname()
    try:
        # "special tactics" for getting instance data inside EC2
        instance_data = subprocess.check_output(
            ["curl", "--silent", "http://169.254.169.254/latest/dynamic/instance-identity/document"])
        # convert from json to dict
        instance_data = json.loads(instance_data)
        # get the instanceId
        if 'instanceId' in instance_data:
            instance_id = instance_data['instanceId']
    except:
        pass

    return instance_id


def ensure_directory_exists(directory_path):
    """
    Recursively generate missing directories as needed
    :param directory_path:
    :return:
    """
    if not os.path.exists(directory_path):

        try:
            os.makedirs(directory_path)
        except OSError as exc:
            if exc.errno == errno.EEXIST and os.path.isdir(directory_path):
                pass
            else:
                raise


class ResourceMonitor:
    def __init__(self, output_dir, interval, aws, alarm_interval=60, s3_upload_bucket=None, s3_upload_path=None,
                 s3_upload_interval=300, logfile=None):

        self.output_dir = output_dir
        datetime_string = get_datetime_string()
        date = get_date_string()
        if aws:
            instance_identifier = get_instance_identification()
            self.log_filename = "log_{}_{}.txt".format(datetime_string, instance_identifier)
        else:
            instance_identifier = None
            self.log_filename = "log_{}.txt".format(datetime_string)

        self.log_path = os.path.join(self.output_dir, self.log_filename)

        self.primary_partition = None
        self.set_primary_partition(self.find_unix_primary_partition())

        self.history_size = max(1, int(round(alarm_interval / interval)))
        self.history = deque()
        self.update_history(self.get_resource_data())

        self.interval = interval

        self.headers = {"time_elapsed_s": 0,
                        "cpu_percent": 1,
                        "virtual_memory_total_gb": 2,
                        "virtual_memory_percent": 3,
                        "swap_memory_total_gb": 4,
                        "swap_memory_percent": 5,
                        "io_activity_read_mb": 6,
                        "io_activity_write_mb": 7,
                        "io_activity_read_count": 8,
                        "io_activity_write_count": 9,
                        "disk_usage_total_gb": 10,
                        "disk_usage_percent": 11}

        self.normalized_types = {"io_activity_read_mb",
                                 "io_activity_write_mb",
                                 "io_activity_read_count",
                                 "io_activity_write_count"}

        self.start_time = None
        self.counter = 0

        if s3_upload_bucket is not None:
            s3_upload_bucket = s3_upload_bucket.lstrip("s3://")

        self.upload_to_s3 = s3_upload_bucket is not None and s3_upload_path is not None
        if self.upload_to_s3:
            self.s3_upload_bucket = s3_upload_bucket
            self.s3_upload_path = s3_upload_path.format(
                instance_id=instance_identifier, timestamp=datetime_string, date=date).lstrip("/")

        self.s3_upload_interval = s3_upload_interval
        self.app_logfile = logfile
        #     Threading stuff
        self.stop_event = threading.Event()

    def update_history(self, data):
        self.history.append(data)

        if len(self.history) > self.history_size:
            self.history.popleft()

    def log(self, msg):
        if self.app_logfile is None:
            print(msg, file=sys.stderr)
        else:
            with open(self.app_logfile, 'a') as logfile:
                print(msg, file=logfile)

    def launch(self):
        ensure_directory_exists(self.output_dir)
        self.log("Writing to log file: %s" % os.path.abspath(self.log_path))

        checkpoint_time = time()
        upload_time = time()
        self.start_time = checkpoint_time
        self.write_header()
        while not self.stop_event.is_set():
            if time() - checkpoint_time > self.interval:

                # get data and write to file
                data = self.get_resource_data()
                self.update_history(data)
                line = self.format_data_as_line(data)
                with open(self.log_path, 'a') as file:
                    file.write(line)

                self.counter += 1
                checkpoint_time = time()

                # upload to s3 (if appropriate)
                if self.upload_to_s3 and time() - upload_time > self.s3_upload_interval:
                    try:
                        self.upload_data_to_s3()
                    except Exception as e:
                        # do not die
                        self.log("Error uploading to S3: {}".format(e))
                        self.s3_upload_interval = self.s3_upload_interval * 2
                        self.log("Changing upload interval to: {}s".format(self.s3_upload_interval))
                    upload_time = time()

                if self.interval > 1:
                    sleep(1)

    def background_launch(self):
        """Start background thread for resource monitoring """
        thread = threading.Thread(target=self.launch, args=())
        thread.daemon = True
        thread.start()

    def kill(self):
        self.stop_event.set()

    @staticmethod
    def list_primary_partitions():
        disk_partitions = psutil.disk_partitions()

        return disk_partitions

    def set_primary_partition(self, partition_name):
        partition_name = os.path.basename(partition_name)
        self.primary_partition = partition_name

    @staticmethod
    def find_unix_primary_partition():
        primary_partition = None
        disk_partitions = psutil.disk_partitions()

        for partition in disk_partitions:
            if partition.mountpoint == "/":
                primary_partition = partition.device
                break

        return primary_partition

    def write_header(self):
        with open(self.log_path, "w") as file:
            header_line = [item[0] for item in sorted(self.headers.items(), key=lambda x: x[1])]
            header_line = "\t".join(header_line) + "\n"
            file.write(header_line)

    def get_resource_data(self):
        data = dict()

        data["time_elapsed_s"] = time()

        cpu_percent = psutil.cpu_percent()
        data["cpu_percent"] = cpu_percent

        virtual_memory = psutil.virtual_memory()
        data["virtual_memory_total_gb"] = virtual_memory.total / (1024 ** 3)
        data["virtual_memory_percent"] = virtual_memory.percent

        swap_memory = psutil.swap_memory()
        data["swap_memory_total_gb"] = swap_memory.total / (1024 ** 3)
        data["swap_memory_percent"] = swap_memory.percent

        io_activity = psutil.disk_io_counters(perdisk=True)
        if len(io_activity.keys()) == 1:
            self.primary_partition = list(io_activity.keys())[0]
        data["io_activity_read_mb"] = io_activity[self.primary_partition].read_bytes / (1024 ** 2)
        data["io_activity_write_mb"] = io_activity[self.primary_partition].write_bytes / (1024 ** 2)
        data["io_activity_read_count"] = io_activity[self.primary_partition].read_count
        data["io_activity_write_count"] = io_activity[self.primary_partition].write_count

        disk_usage = psutil.disk_usage("/")
        data["disk_usage_total_gb"] = disk_usage.total / (1024 ** 3)
        data["disk_usage_percent"] = disk_usage.percent

        return data

    def format_data_as_line(self, data):
        self.log("intervals elapsed: %d" % self.counter)

        line = list()
        for item in sorted(self.headers.items(), key=lambda x: x[1]):
            key = item[0]
            value = data[key]

            # If psutil gives absolute (cumulative) values, then subtract the baseline for each interval
            if key in self.normalized_types:
                value -= self.history[-2][key]

            if key == "time_elapsed_s":
                value -= self.start_time

            line.append("%.3f" % value)

        line = "\t".join(line) + "\n"

        return line

    def upload_data_to_s3(self):
        endpoint = os.path.join(self.s3_upload_path, self.log_filename)
        self.log("Uploading {} to s3://{}/{}".format(self.log_path, self.s3_upload_bucket, endpoint))
        s3 = boto3.resource('s3')
        s3.meta.client.upload_file(self.log_path, self.s3_upload_bucket, endpoint,
                                   ExtraArgs={
                                       'ACL': 'bucket-owner-full-control'})  # this enables upload cross-region (maybe)
