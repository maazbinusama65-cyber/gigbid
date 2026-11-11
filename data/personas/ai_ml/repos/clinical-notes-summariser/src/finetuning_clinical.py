from peft import LoraConfig, get_peft_model

def sync_clinical(base):
    cfg = LoraConfig(r=16, lora_alpha=32, target_modules=['q_proj', 'v_proj'], lora_dropout=0.05)
    return get_peft_model(base, cfg)
