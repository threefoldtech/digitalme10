from Jumpscale import j

# GENERATED CODE CAN CHANGE

SCHEMA = """
# Sell Order
@url = digitalme.dnsrecord
type = "" (S)   # A, AAAA, NS, MX, CNAME, TXT, PTR
val = "" (S)


"""


bcdb = j.data.bcdb.latest
schema = j.data.schema.get_from_text(SCHEMA)
Index_CLASS = bcdb._BCDBModelIndexClass_generate(schema, __file__)
MODEL_CLASS = bcdb._BCDBModelClass


class dns(Index_CLASS, MODEL_CLASS):
    def __init__(self):
        MODEL_CLASS.__init__(self, bcdb=bcdb, schema=schema)
        self.write_once = False
        self._init()
