class _AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False


ANY_TYPE = _AnyType("*")


class InversionDemoLazySwitch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "on_false": (ANY_TYPE, {"forceInput": True}),
                "on_true": (ANY_TYPE, {"forceInput": True}),
                "switch": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = (ANY_TYPE,)
    RETURN_NAMES = ("*",)
    FUNCTION = "pick"
    CATEGORY = "LTX2/Compat"

    def pick(self, on_false, on_true, switch):
        return (on_true if switch else on_false,)


NODE_CLASS_MAPPINGS = {
    "InversionDemoLazySwitch": InversionDemoLazySwitch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "InversionDemoLazySwitch": "Bypass Enhancer Switch",
}
