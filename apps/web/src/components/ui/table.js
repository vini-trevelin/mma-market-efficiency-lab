import { jsx as _jsx } from "react/jsx-runtime";
export function Table({ className = "", ...props }) {
    return (_jsx("div", { className: "table-wrap", children: _jsx("table", { className: `table ${className}`.trim(), ...props }) }));
}
export function TableHeader(props) {
    return _jsx("thead", { ...props });
}
export function TableBody(props) {
    return _jsx("tbody", { ...props });
}
export function TableRow(props) {
    return _jsx("tr", { ...props });
}
export function TableHead(props) {
    return _jsx("th", { ...props });
}
export function TableCell(props) {
    return _jsx("td", { ...props });
}
