import onnxruntime as ort

sess = ort.InferenceSession('model.onnx', providers=['CPUExecutionProvider'])

def run_factory(x):
    return sess.run(None, {sess.get_inputs()[0].name: x})[0]
