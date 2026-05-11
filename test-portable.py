from menu_lens_portable import process_menu

with open("menu.jpg", "rb") as f:
    image_bytes = f.read()

result = process_menu(image_bytes)
print(result)