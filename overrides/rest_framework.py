from rest_framework.response import Response

class APIResponse(Response):
    def __init__(self, message: object, status: object, **kwargs: object) -> object:
        response_data = {
            'message': message,
        }

        data = kwargs.get("data")
        response_data.update({"data": data}) if data else None

        if status in range(200, 299):
            response_data["status"] = "success"
        else:
            response_data["status"] = "failed"

        super().__init__(response_data, status=status)