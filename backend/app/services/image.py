import base64

def image_to_data_url(data:bytes, content_type:str)->str:
    return f'data:{content_type};base64,' + base64.b64encode(data).decode()
