import torch

def export_onnx(model, path='defect.onnx'):
    dummy = torch.randn(1, 3, 512, 512)
    torch.onnx.export(model, dummy, path, opset_version=17)
