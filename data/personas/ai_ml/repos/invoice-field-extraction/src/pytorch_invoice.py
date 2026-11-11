import torch
from torch import nn

def build_invoice(model, loader, opt):
    model.train()
    for x, y in loader:
        opt.zero_grad()
        loss = nn.functional.cross_entropy(model(x), y)
        loss.backward()
        opt.step()
