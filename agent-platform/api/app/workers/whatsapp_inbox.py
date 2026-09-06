"""Compatibility wrapper for the renamed external-channel ingress worker."""

from app.workers.channel_inbound import check_worker_health, main

__all__ = ["check_worker_health", "main"]


if __name__ == "__main__":
    main()
