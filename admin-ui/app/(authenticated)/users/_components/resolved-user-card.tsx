/**
 * <ResolvedUserCard> — renders the user resolved from an identifier
 * lookup. Shows the canonical user_id + the identifier that matched, with
 * a button to open the detail drawer (Phase G — for now placeholder).
 */
import { Eye } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { shortId } from "@/lib/utils";

interface Props {
  userId: string;
  tenantId: string;
  identifierType: string;
  identifierValue: string;
}

export function ResolvedUserCard({
  userId,
  tenantId,
  identifierType,
  identifierValue,
}: Props) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>{shortId(userId, "usr")}</CardTitle>
          <Badge tone="success">Active</Badge>
        </div>
      </CardHeader>
      <CardBody>
        <dl className="grid grid-cols-2 gap-3 text-[12px]">
          <div>
            <dt className="text-[--color-text-3]">User ID</dt>
            <dd className="font-mono text-[12px]">{userId}</dd>
          </div>
          <div>
            <dt className="text-[--color-text-3]">Tenant</dt>
            <dd className="font-mono text-[12px]">{shortId(tenantId, "ten")}</dd>
          </div>
          <div>
            <dt className="text-[--color-text-3]">Resolved by</dt>
            <dd>{identifierType}</dd>
          </div>
          <div>
            <dt className="text-[--color-text-3]">Identifier</dt>
            <dd className="font-mono">{identifierValue}</dd>
          </div>
        </dl>
      </CardBody>
      <CardFooter>
        <Button variant="outline" disabled title="Detail drawer ships in Phase G">
          <Eye className="h-3.5 w-3.5" />
          View detail
        </Button>
      </CardFooter>
    </Card>
  );
}
