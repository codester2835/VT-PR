lines = []
with open("manifest.xml", "r") as file:
	lines = [line for line in file if '<c d="' not in line]

with open("manifest.xml", "w") as file:
	file.writelines(lines)