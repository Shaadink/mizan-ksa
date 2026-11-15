// Local visual check only: the Command Center without the Fabric auth gate (snapshot data).
import { createRoot } from "react-dom/client";

import { CommandCenter } from "./command-center/CommandCenter";

createRoot(document.getElementById("root")!).render(<CommandCenter />);
