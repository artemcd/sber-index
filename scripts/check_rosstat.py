from build_rosstat_context import oktmo, unique_value

assert oktmo("1 512 000") == "01512000"
assert oktmo("79-701-000-000") == "79701000"
assert unique_value([]) == (None, "missing")
assert unique_value([0]) == (0, "ok")
assert unique_value([123, 123]) == (123, "ok")
assert unique_value([123, 456]) == (None, "conflict")
assert unique_value([float("nan")])[1] == "invalid"
print("ОКТМО, пропуски, нули и конфликтующие наблюдения — OK")
