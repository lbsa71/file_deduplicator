"""Apply process limits before starting an untrusted media decoder."""

import os
import resource
import sys


def main():
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024**2, 16 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    os.environ["VIPS_CONCURRENCY"] = "1"
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
