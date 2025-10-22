#!/bin/bash

# Redis Setup Commands for VIMP Project

echo "=== Redis Installation Test ==="

# Test Redis connection
echo "Testing Redis connection..."
redis-cli ping

if [ $? -eq 0 ]; then
    echo "Redis is running successfully!"
else
    echo "Redis is not running. Please start Redis service."
    echo "Try: sudo service redis-server start (Linux)"
    exit 1
fi

echo -e "\n=== Redis Configuration Check ==="

# Check Redis version
echo "Redis version:"
redis-cli --version

# Check Redis server info
echo -e "\nRedis server info:"
redis-cli INFO server | head -5

# Test basic operations
echo -e "\n=== Testing Redis Operations ==="

# Set a test key
redis-cli SET vimp_test "Hello from VIMP"
echo "Set test key: vimp_test = 'Hello from VIMP'"

# Get the test key
result=$(redis-cli GET vimp_test)
echo "Retrieved test key: $result"

# Set key with expiration
redis-cli SETEX vimp_temp 60 "Temporary value"
echo "Set temporary key with 60s expiration"

# Check TTL
ttl=$(redis-cli TTL vimp_temp)
echo "TTL for temporary key: $ttl seconds"

# Clean up test keys
redis-cli DEL vimp_test vimp_temp
echo "Cleaned up test keys"