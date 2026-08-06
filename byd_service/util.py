from datetime import datetime
import random
import re
import uuid
from contextlib import contextmanager

from django.core.cache import cache


class ByDObjectLockedError(Exception):
	"""
		Raised when a ByD business object cannot be written because it is locked
		(typically by our own integration user via a concurrent or recent API call).
	"""
	pass


# Substrings ByD uses to signal an enqueue/lock conflict. Matched case-insensitively.
_LOCK_ERROR_SIGNATURES = (
	"locking object not possible",
	"object locked by",
	"locked by",
	"object is locked",
)


def is_byd_lock_error(error) -> bool:
	"""
		Return True if the given exception/text represents a ByD object-lock conflict.
		Covers both SAP's wording ("Locking object not possible / object locked by ...")
		and our own ByDObjectLockedError sentinel.
	"""
	if isinstance(error, ByDObjectLockedError):
		return True
	text = str(error).lower()
	return any(signature in text for signature in _LOCK_ERROR_SIGNATURES)


# Redis-backed mutex used to serialise ByD writes per purchase order.
PO_LOCK_PREFIX = "byd:po-write-lock"
# Auto-expires so a dead worker can't hold the lock forever. Must exceed
# Q_CLUSTER['timeout'] (300s): a worker can legitimately be alive that long, and
# a lock that expires while its holder is still working lets a second worker in.
PO_LOCK_TTL = 420


@contextmanager
def po_write_lock(po_id, ttl: int = PO_LOCK_TTL):
	"""
		Serialise ByD writes for a single purchase order across django-q workers.

		Because every notification/invoice for a PO updates the same underlying
		Inbound Delivery Request / PO object, concurrent writes under the same SAP
		user lock each other out. This mutex ensures only one task touches a given
		PO at a time. Yields True if the lock was acquired, False otherwise.
	"""
	key = f"{PO_LOCK_PREFIX}:{po_id}"
	# Unique ownership token: release must only delete a lock this worker still
	# holds. Without it, a worker whose lock already expired would delete the
	# lock a *different* worker now owns, silently disabling the mutex.
	token = uuid.uuid4().hex
	# cache.add only sets the key if it does not already exist -> atomic mutex.
	acquired = cache.add(key, token, ttl)
	try:
		yield acquired
	finally:
		if acquired and cache.get(key) == token:
			cache.delete(key)


def compute_backoff_seconds(retry_count: int, base: int = 30, cap: int = 900,
							jitter_ratio: float = 0.25) -> int:
	"""
		Exponential backoff with jitter (capped) for spacing out lock retries so
		repeated attempts wait for the lock to clear instead of dog-piling.
	"""
	delay = min(base * (2 ** max(retry_count, 0)), cap)
	return int(delay + random.uniform(0, delay * jitter_ratio))


def to_python_time(byd_time):
	# Extract timestamp using regular expression
	match = re.search(r'\d+', byd_time)
	timestamp = int(match.group()) / 1000
	# Convert timestamp to datetime object
	return datetime.utcfromtimestamp(timestamp)


def format_datetime_to_iso8601(dt: datetime) -> str:
	"""
		Convert a datetime object to an ISO 8601 string with UTC offset ('Z').
	"""
	return dt.strftime("%Y-%m-%dT%H:%M:%S")


def ordinal(number):
	if 10 <= number % 100 <= 20:
		suffix = 'th'
	else:
		suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th')
	return str(number) + suffix