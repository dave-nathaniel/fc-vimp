# Miscellaneous methods to be used throughout the app
import os


# Convert base64 string to image and save to given path
def base64_to_image(base64_string, path, name):
	import base64
	try:
		# Get the part after the comma, if there is one
		base64_string = base64_string.split(',')[-1]
		# Decode the base64 string into bytes
		image_bytes = base64.b64decode(base64_string)
		if not os.path.exists(path):
			os.makedirs(path)
		fullpath = os.path.join(path, name)
		# Write the bytes to a file
		with open(fullpath, "wb") as f:
			f.write(image_bytes)
		return fullpath
	except Exception as e:
		raise Exception(f"Error decoding base64 string or identifying image: {e}")
