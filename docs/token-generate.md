export AINEKIO_ROBOT_ID='ainekio-01'
  export AINEKIO_ROBOT_TOKEN="$(openssl rand -hex 32)"
  export AINEKIO_ENVIRONMENT_ADAPTER_TOKEN="$(openssl rand -hex 32)"

  printf 'ROBOT PAIRING TOKEN: %s\n' "$AINEKIO_ROBOT_TOKEN"

  ./Master/start-physical-gateway.sh

greggles@DNDIY:~/Ainekio$ export AINEKIO_ROBOT_ID='ainekio-01'
  export AINEKIO_ROBOT_TOKEN="$(openssl rand -hex 32)"
  export AINEKIO_ENVIRONMENT_ADAPTER_TOKEN="$(openssl rand -hex 32)"

  printf 'ROBOT PAIRING TOKEN: %s\n' "$AINEKIO_ROBOT_TOKEN"

  ./Master/start-physical-gateway.sh
ROBOT PAIRING TOKEN: 5f6e1d19d0021864b3a76afefd6de027d5c10540ad4e6df7dab8a043f8f1597b
Starting the physical Ainekio gateway.
  Robot listener:     ws://0.0.0.0:8790/robot
  Environment bridge: ws://0.0.0.0:8790/environment
  Local dashboard:    http://127.0.0.1:8791/
  Brain LAN addresses: 192.168.0.44 172.17.0.1 
  Robot ID:           ainekio-01
  Runtime data:       /home/greggles/Ainekio/build/gateway/physical
Press Ctrl+C to stop the gateway.
Ainekio robot gateway: ws://0.0.0.0:8790/robot
Ainekio environment:  ws://0.0.0.0:8790/environment
Ainekio dashboard:    http://127.0.0.1:8791/




