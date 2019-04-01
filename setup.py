#!/usr/bin/env python
"""Create setup script for pip installation of TaskManager"""
########################################################################
# File: setup.py
#  executable: setup.py
#
# Author: Andrew Bailey
# History: 03/29/19 Created
########################################################################

from setuptools import setup, find_packages


def main():
    setup(
        name="taskManager",
        version="0.0.5",
        description='Task manager to keep track of compute resources and send email update when command exits',
        url='https://github.com/rlorigro/TaskManager',
        author='Ryan Lorig-Roach, Andrew Bailey',
        license='MIT',
        setup_requires=["pytest-runner"],
        tests_require=["pytest"],
        author_email='rlorigro@ucsc.edu, andbaile@ucsc.com',
        packages=find_packages(),
        scripts=['bin/taskManager'],
        install_requires=['psutil>=5.6.1',
                          'boto3>=1.9',
                          'pytest>=4.3.1',
                          'py3helpers>=0.2.4'],
        zip_safe=True
    )


if __name__ == "__main__":
    main()
    raise SystemExit
