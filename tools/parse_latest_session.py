import json

with open('logs/sesiones/127_0_0_1_16769_20261011_193808_orden.jsonl', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        op = data.get('opcode')
        if op in (18, 34, 11, 7, 5, 6, 10, 13, 27):
            print(f"{data['t']:.2f} {data['dir']} op=0x{op:04x}({op}) len={data['len']} hex={data.get('hex')}")
