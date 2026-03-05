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


class CM_FloatToInt:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "a": ("FLOAT", {"default": 0.0}),
            }
        }

    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("INT",)
    FUNCTION = "convert"
    CATEGORY = "LTX2/Compat"

    def convert(self, a):
        return (int(round(float(a))),)


class ImpactExecutionOrderController:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "signal": (ANY_TYPE, {"forceInput": True}),
                "value": (ANY_TYPE, {"forceInput": True}),
            }
        }

    RETURN_TYPES = (ANY_TYPE, ANY_TYPE)
    RETURN_NAMES = ("signal", "value")
    FUNCTION = "passthrough"
    CATEGORY = "LTX2/Compat"

    def passthrough(self, signal, value):
        return (signal, value)


NODE_CLASS_MAPPINGS = {
    "InversionDemoLazySwitch": InversionDemoLazySwitch,
    "CM_FloatToInt": CM_FloatToInt,
    "ImpactExecutionOrderController": ImpactExecutionOrderController,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "InversionDemoLazySwitch": "Bypass Enhancer Switch",
    "CM_FloatToInt": "Float To Int (Compat)",
    "ImpactExecutionOrderController": "Execution Order Controller (Compat)",
}
