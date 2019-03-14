lapis = require "lapis"
redis = require 'redis'
config = require("lapis.config").get!
util = require "lapis.util"

class extends lapis.Application
  "/": =>
    client = redis.connect(config.gedis_host, config.gedis_port)
    client["gedis"] = redis.command("default.notary_actor.start_page")
    client.gedis(client)
    
  "/register": =>
    ngx.req.read_body()
    data = ngx.req.get_body_data()

    client = redis.connect(config.gedis_host, config.gedis_port)
    client["gedis"] = redis.command("default.notary_actor.register")

    header = {
      "response_type": "json"
    }
    response = {
      "json": util.from_json(client.gedis(client, util.to_json(data), util.to_json(header))),
      "status": 200
    }
    return response
    

  "/get": =>
    ngx.req.read_body()
    client = redis.connect(config.gedis_host, config.gedis_port)
    client["gedis"] = redis.command("default.notary_actor.get")

    args = {
      "hash": @params.hash
    }
    header = {
      "response_type": "json"
    }
    response = {
      "json": util.from_json(client.gedis(client, util.to_json(args), util.to_json(header))),
      "status": 200
    }
    return response