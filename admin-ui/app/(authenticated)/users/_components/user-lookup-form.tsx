/**
 * <UserLookupForm> — search controls for the Users page.
 *
 * Submits to /users?type=…&value=… as a plain server-routed navigation,
 * letting the page server-component resolve the identifier and render the
 * result. No client state besides the controlled inputs.
 */
"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const IDENTIFIER_TYPES: { value: string; label: string }[] = [
  { value: "phone", label: "Phone" },
  { value: "email", label: "Email" },
  { value: "account_number", label: "Account #" },
  { value: "card_number", label: "Card #" },
];

export function UserLookupForm({
  initialType,
  initialValue,
}: {
  initialType: string;
  initialValue: string;
}) {
  const router = useRouter();
  const [type, setType] = React.useState(initialType);
  const [value, setValue] = React.useState(initialValue);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    // Phone numbers are stored without whitespace / dashes / parens — strip
    // them here so an operator pasting "+27 82 555 0001" still resolves.
    const canonical =
      type === "phone" ? trimmed.replace(/[\s\-().]/g, "") : trimmed;
    const params = new URLSearchParams({ type, value: canonical });
    router.push(`/users?${params.toString()}`);
  };

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-wrap items-end gap-3 rounded-lg border border-[--color-border] bg-[--color-surface-1] p-4"
    >
      <div className="w-[140px]">
        <Label htmlFor="lookup-type">Identifier</Label>
        <div className="mt-1">
          <Select value={type} onValueChange={setType}>
            <SelectTrigger id="lookup-type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {IDENTIFIER_TYPES.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="min-w-[260px] flex-1">
        <Label htmlFor="lookup-value">Value</Label>
        <div className="mt-1">
          <Input
            id="lookup-value"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="+27 82 555 0142"
            autoComplete="off"
          />
        </div>
      </div>
      <Button type="submit" size="md">
        <Search className="h-3.5 w-3.5" />
        Lookup
      </Button>
    </form>
  );
}
