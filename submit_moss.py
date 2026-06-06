"""
MOSS submission script for LLM Privacy Guard
Usage:
  1. Register: send email to moss@moss.stanford.edu with body:
     registeruser
     mail your@email.com
  2. Replace USER_ID below with the ID you receive
  3. Run: python submit_moss.py
  4. Open the URL it prints
"""

import mosspy
import glob

USER_ID = 521435005

moss = mosspy.Moss(USER_ID, "python")

# Submit all Python files in privacy_engine/
for f in glob.glob("privacy_engine/*.py"):
    moss.addFile(f)

print("Submitting to MOSS...")
url = moss.send()
print()
print("Results:", url)
print("Open this URL in your browser to see the similarity report.")
