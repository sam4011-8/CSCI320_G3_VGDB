#
# Small program for creating data for table population
#

# Prompt data to be created
#   Type, Amount, Upper/Lower limits

# Generate data
import random
import csv
from pathlib import Path

# 1. Ask for the type of data
print("Choose the type of data:")
print("1 - Integer")
print("2 - Number with one decimal place")

data_type = input("Enter 1 or 2: ")

# 2. Ask for the number of entries
num_entries = int(input("How many entries would you like? "))

# 3. Ask for the lower and upper limits
lower_limit = float(input("Enter the lower limit: "))
upper_limit = float(input("Enter the upper limit: "))

# 4. Generate the data
data = []

for _ in range(num_entries):
    if data_type == "1":
        value = random.randint(
            int(lower_limit), int(upper_limit)
        )
    elif data_type == "2":
        value = round(
            random.uniform(lower_limit, upper_limit), 1
        )
    else:
        print("Invalid data type selected.")
        exit()

    data.append(value)

# 5. Ask for the output filename
filename = input("Enter the output filename (without .csv): ")
if not filename.lower().endswith(".csv"):
    filename += ".csv"

# 6. Save the data to a CSV file in the same directory
output_path = Path(__file__).resolve().parent / "Data" / filename

# Create the Data folder if it doesn't already exist
output_path.parent.mkdir(parents=True, exist_ok=True)

with open(output_path, "w", newline="") as file:
    writer = csv.writer(file)
    writer.writerow(["Value"])
    for value in data:
        writer.writerow([value])

print(f"\n{num_entries} entries saved to: {output_path}")