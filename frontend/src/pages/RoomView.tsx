// One room: echo time chart, listen (voice / clap), what-if materials, panorama.
// TODO: port the room card from frontend/prototypes/acoustics/index.html.
import { useParams } from "react-router-dom";
export default function RoomView() {
  const { sid, rid } = useParams();
  return <main><h1>Room {rid} in {sid}</h1><p>TODO: EchoChart, Listen, WhatIf</p></main>;
}
