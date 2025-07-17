from datetime import datetime
import re

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