from PIL import Image
from transformers import pipeline

# 1. Load the model (downloads automatically on the first run)
pipe = pipeline(task="depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf")

# 2. Tell the script which local file to load
image_file = "example-boxes-in-a-truck.png"
image = Image.open(image_file)

# 3. Predict the depth map
result = pipe(image)

# 4. Save the generated depth image to your folder
depth_map = result["depth"]
depth_map.save("my_photo_depth.png")

print("Depth estimation complete! Output saved as 'my_photo_depth.png'.")