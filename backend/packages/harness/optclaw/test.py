from config.paths import Path
print(Path(__file__).resolve())
print(Path(__file__).resolve().parents[0])
print(Path(__file__).resolve().parents[3])