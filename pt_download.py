import os
from rfdetr import RFDETRNano

weight_dir = "/home/try/code/label-platform/weights"
os.makedirs(weight_dir, exist_ok=True)

weight_path = os.path.join(
    weight_dir,
    "rf-detr-nano.pth"
)

print(f"Downloading RF-DETR Nano weights to: {weight_path}")

model = RFDETRNano(
    pretrain_weights=weight_path
)

print("Download finished!")
print(f"Weight saved at: {weight_path}")