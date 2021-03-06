


from Jumpscale import j

# JSBASE = j.application.JSBaseClass

class GedisClientGenerated():

    def __init__(self,client):
        # JSBASE.__init__(self)
        self._client = client
        self._redis = client._redis

    {# generate the actions #}
    {% for name,cmd in obj.cmds.items() %}

    def {{name}}(self{{cmd.args_client}}):
        {% if cmd.comment != "" %}
        '''
{{cmd.comment_indent2}}
        '''
        {% endif %}
        cmd_name = "{{obj.namespace.lower()}}.{{obj.name.lower()}}.{{name}}" #what to use when calling redis
        {% if cmd.schema_in != None %}
        #schema in exists
        schema_in = j.data.schema.get_from_url_latest(url="{{cmd.schema_in.url}}")
        args = schema_in.new()

        {% for prop in cmd.schema_in.properties %}
        args.{{prop.name}} = {{prop.name}}
        {% endfor %}

        id2 = id if not callable(id) else None #if id specified will put in id2 otherwise will be None
        res = self._redis.execute_command(cmd_name,j.data.serializers.msgpack.dumps([id2, args._data]))

        {% else %}  #is for non schema based

        {% set args = cmd.cmdobj.args if cmd.cmdobj.args else [] %}

        {% if args|length == 0 %}
        res =  self._redis.execute_command(cmd_name)
        {% else %}
        # send multi args with no prior knowledge of schema
        res = self._redis.execute_command(cmd_name, {{ cmd.args_client.lstrip(',')}})
        {% endif %} #args bigger than []
        {% endif %} #end of test if is schema_in based or not

        {% if cmd.schema_out != None %}
        # print("{{cmd.schema_out.url}}")
        schema_out = j.data.schema.get_from_url_latest(url="{{cmd.schema_out.url}}")
        if isinstance(res, list):
            res2 = list(map(lambda x: schema_out.get(data=x), res))
        else:
            res2 = schema_out.get(data=res)
        {% else %}
        res2 = res
        {% endif %}

        return res2


    {% endfor %}

