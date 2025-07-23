import re
import os
from pathlib import Path

def strings(filename, directory, min_len=4):
    """Extract strings from memory dump file"""
    try:
        input_path = Path(directory) / filename
        output_path = Path(directory) / "strings.txt"
        
        with open(input_path, 'rb') as infile:
            data = infile.read()
            
        # Extract ASCII strings
        ascii_strings = re.findall(b'[\x20-\x7E]{' + str(min_len).encode() + b',}', data)
        
        with open(output_path, 'w', encoding='utf-8', errors='ignore') as outfile:
            for string in ascii_strings:
                try:
                    decoded = string.decode('ascii', errors='ignore')
                    if len(decoded) >= min_len:
                        outfile.write(decoded + '\n')
                except:
                    continue
                    
        return len(ascii_strings)
        
    except Exception as e:
        return 0
