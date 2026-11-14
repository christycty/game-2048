import { useState } from "react";
import "./Board.css"


function Tile({x, y, value}) {

    return (
        <div className="tile">
            tile at {x}, {y}, value {value}
        </div>
    );
}


function Board() {
    const [tiles, setTiles] = useState(null);

    return (
        <>
            <div className="board-background">
                <div className="board">
                    <Tile x={1} y={1} value={1}></Tile>
                </div>
            </div>
        </>
    );
}

export default Board;