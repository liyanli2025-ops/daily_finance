import sys
sys.path.insert(0, '.')

try:
    from app.main import app
    print("Import successful!")
except Exception as e:
    print(f"Import error: {e}")
    import traceback
    traceback.print_exc()
