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
                    {
                        // TODO: use actual tile info to map later 
                        [...Array(16).keys()].map(key => <Tile x={key/4} y={key%4} value={key} key={key} ></Tile>)
                    }
                </div>
            </div>
        </>
    );
}

export default Board;