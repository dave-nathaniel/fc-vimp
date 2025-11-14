#!/bin/bash

# Script to create .env file from .defaults.env and .overrides.env
# Variables in .overrides.env take precedence over .defaults.env

set -e

# Get the script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../" && pwd)"

echo "PROJECT_ROOT: $PROJECT_ROOT"

DEFAULTS_FILE="$PROJECT_ROOT/.defaults.env"
OVERRIDES_FILE="$PROJECT_ROOT/.overrides.env"
OUTPUT_FILE="$PROJECT_ROOT/.env"

# Check if defaults file exists
if [ ! -f "$DEFAULTS_FILE" ]; then
    echo "Error: .defaults.env not found at $DEFAULTS_FILE"
    exit 1
fi

# Create output file (will overwrite if exists)
> "$OUTPUT_FILE"

# Write a warning message that the .env should not be edited directly, instead use .overrides.env and .defaults.env
echo "" >> "$OUTPUT_FILE"
echo "# !!!! WARNING  !!!! " >> "$OUTPUT_FILE"
echo "#   THE .ENV FILE SHOULD NOT BE EDITED DIRECTLY, INSTEAD USE .OVERRIDES.ENV AND .DEFAULTS.ENV TO OVERRIDE VARIABLES" >> "$OUTPUT_FILE"
echo "#   TO EDIT THE .ENV FILE, EDIT THE .OVERRIDES.ENV AND .DEFAULTS.ENV FILES THEN RUN THIS SCRIPT" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"

# Extract variable assignments from overrides file (if it exists)
declare -A OVERRIDE_VARS
if [ -f "$OVERRIDES_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip empty lines and comments
        if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
            continue
        fi
        
        # Extract key-value pairs
        if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
            key="${BASH_REMATCH[1]}"
            value="${BASH_REMATCH[2]}"
            OVERRIDE_VARS["$key"]="$value"
        fi
    done < "$OVERRIDES_FILE"
fi

# Process defaults file line by line
while IFS= read -r line || [ -n "$line" ]; do
    # Skip empty lines and comments - copy them as-is
    if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
        echo "$line" >> "$OUTPUT_FILE"
        continue
    fi
    
    # Check if line contains a variable assignment
    if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
        key="${BASH_REMATCH[1]}"
        default_value="${BASH_REMATCH[2]}"
        
        # Check if this key exists in overrides
        if [[ -n "${OVERRIDE_VARS[$key]:-}" ]]; then
            # Use override value
            echo "$key=${OVERRIDE_VARS[$key]}" >> "$OUTPUT_FILE"
        else
            # Use default value
            echo "$line" >> "$OUTPUT_FILE"
        fi
    else
        # Not a variable assignment, copy as-is
        echo "$line" >> "$OUTPUT_FILE"
    fi
done < "$DEFAULTS_FILE"

echo ".env file created successfully at $OUTPUT_FILE"

