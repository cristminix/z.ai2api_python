# Converts OpenAI compatible function calling JSON schema to a prompt that instructs the LLM to return
# a JSON object that is a choice of a function call conforming to one of the functions or a message reply

def convert_schema_to_typescript(schema):
    if not schema:
        return 'any'

    if '$ref' in schema:
        return schema['$ref'].replace('#/definitions/', '')

    schema_type = schema.get('type', '')
    if schema_type == 'string':
        return 'string' if 'enum' not in schema else ' | '.join(f'"{e}"' for e in schema['enum'])
    elif schema_type == 'number':
        return 'number'
    elif schema_type == 'integer':
        return 'number'
    elif schema_type == 'boolean':
        return 'boolean'
    elif schema_type == 'object':
        properties = ' '.join(f"{key}{':' if key in schema.get('required', []) else '?:'} {convert_schema_to_typescript(value)};"
                              for key, value in schema.get('properties', {}).items())
        return f"{{ {properties} }}"
    elif schema_type == 'array':
        return f"{convert_schema_to_typescript(schema.get('items', {}))}[]"
    elif schema_type == 'null':
        return 'null'
    else:
        return 'any'

def convert_function_to_typescript(schema):
    if not schema or schema['type'] != 'function' or 'function' not in schema:
        raise ValueError('Invalid schema: Must be a function schema')

    func = schema['function']
    params = ', '.join(f"{param_name}{':' if param_name in func['parameters'].get('required', []) else '?:'} {convert_schema_to_typescript(param_details)}"
                       for param_name, param_details in func['parameters']['properties'].items())

    return f"function {func['name']}({params}): any;"

def convert_function_call(tools):
    conversion = "// The current environment gives you access to the following functions to use as tools:\n"
    for tool in filter(lambda x: x['type'] == 'function', tools):
        converted = convert_function_to_typescript(tool)
        conversion += converted + '\n'

    conversion += """
// Reply interface structure
interface Reply {
    type: string;
};

// FunctionCall interface extending Reply
// Must match one of the above function definitions
interface FunctionCall extends Reply {
    type: "functionCall";
    name: string; /* function name */
    arguments: {
        name: string;
        value: any;
    }[];
};

// Default reply
// Message interface extending Reply
interface Message extends Reply {
    type: "message";
    content: string; // do not mention the details of your tools 
};

Return a valid JSON object conforming to the Reply interface.
"""

    return conversion

# Sample tool for testing
sample_tool = {
    "type": "function",
    "function": {
      "name": "searchAdobeScriptingAPIDocs",
      "description": "Search Adobe API documentation: classes, methods, properties",
      "parameters": {
        "type": "object",
        "properties": {
          "appName": {
            "type": "string",
            "enum": [
              "illustrator",
              "photoshop",
              "indesign",
              "xd",
              "incopy",
              "premierePro",
              "aftereffects",
              "animate",
              "bridge"
            ],
            "description": "Host app name"
          },
          "searchTerms": {
            "type": "string",
            "description": "Search terms"
          },
          "filter": {
            "type": "string",
            "description": "Limit results by type",
            "enum": ["class", "method", "parameter"]
          },
        },
        "required": ["appName", "searchTerms"]
      }
    }
}

# Test the conversion function with the sample tool
typescript_conversion = convert_function_call([sample_tool])
typescript_conversion
