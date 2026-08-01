import matplotlib.pyplot as plt
import pandas as pd

# Dummy data
data = [
    ["1", "251017002001", "Alice", "P", "P", "P", "P", "P"],
    ["2", "251017002002", "Bob", "", "P", "", "P", ""],
    ["3", "251017002003", "Charlie", "P", "", "P", "", "P"],
]
cols = ["Sl NO", "Student_ID", "Student_NAME", "Subj 1", "Subj 2", "Subj 3", "Subj 4", "Subj 5"]
df = pd.DataFrame(data, columns=cols)

fig, ax = plt.subplots(figsize=(10, 2))
ax.axis('tight')
ax.axis('off')

# Render table
table = ax.table(cellText=df.values, colLabels=df.columns, loc='center', cellLoc='center')
table.auto_set_font_size(False)
table.set_fontsize(10)
table.scale(1, 1.5)

# Save to file
plt.savefig("test_table.png", bbox_inches='tight', dpi=150)
print("Saved test_table.png")
