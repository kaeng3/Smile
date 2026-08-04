# -*- coding: utf-8 -*-
import codecs

def fix_encoding():
    print("Reading ai_commentator.py...")
    try:
        # Read as bytes
        with open('ai_commentator.py', 'rb') as f:
            data = f.read()
            
        # Try decoding with cp949 first, then utf-8, then ignoring errors
        try:
            text = data.decode('utf-8')
            print("Successfully decoded as UTF-8 directly.")
        except UnicodeDecodeError:
            try:
                # Let's try decoding with utf-8, but replace invalid parts
                text = data.decode('utf-8', errors='replace')
                print("Decoded as UTF-8 with replacement.")
            except Exception as e:
                print("Failed to decode:", e)
                return
                
        # Write back as clean UTF-8
        with open('ai_commentator.py', 'w', encoding='utf-8') as f:
            f.write(text)
        print("Successfully wrote ai_commentator.py as clean UTF-8.")
    except Exception as e:
        print("Error during fix:", e)

if __name__ == '__main__':
    fix_encoding()
