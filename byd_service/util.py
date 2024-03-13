from datetime import datetime
import re

def to_python_time(byd_time):
	# Extract timestamp using regular expression
	match = re.search(r'\d+', byd_time)
	timestamp = int(match.group()) / 1000
	# Convert timestamp to datetime object
	return datetime.utcfromtimestamp(timestamp)