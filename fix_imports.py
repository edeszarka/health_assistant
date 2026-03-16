import os

def fix_imports():
    for root, dirs, files in os.walk(r'c:\repok\health_assistant\backend'):
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(root, file)
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                if 'from backend.' in content:
                    content = content.replace('from backend.', 'from ')
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    print(f"Fixed {path}")

if __name__ == '__main__':
    fix_imports()
